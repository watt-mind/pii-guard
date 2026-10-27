"""LoRA SFT of Muse Glimmer 30B on Fireworks Serverless Training, answer-only, no sampling.

Fictional data only. Trains on the chat JSONL from ``training/llm/build_sft.py`` with a
cross-entropy loop on the Fireworks Serverless Training pool, then promotes the final sampler
checkpoint to a LoRA model in the account (downloadable, see ``docs/models.md``).

Why this surface: Muse Glimmer 30B LoRA SFT is promotional ``$0`` on Managed SFT and on
Serverless Training until 2026-11-30 (docs.fireworks.ai/fine-tuning/models). Managed SFT needs
a dataset upload, which the account could not do (``dataset uploads are temporarily
disabled``); Serverless Training takes the rendered tokens directly. **Sampling is billed
separately**, so this script never samples: no base-vs-tuned evaluation in the session.
Evaluation runs on our own vLLM server instead (``deploy/modal/glimmer.py`` with the adapter).

Rendering uses the Fireworks cookbook's port of the model's own chat template
(``training.renderer.muse_glimmer``), the same text vLLM builds from
``chat_template.jinja``: system (with ``Reasoning strength: <strength>.``), user, then the
trained part ``<|start|>assistant`` + `` to=user<|message|>{json}<|eot|>``. Only the answer
carries loss; there is no ``to=self`` reasoning turn, so the model learns to address the user
directly. Serve with the same ``reasoning_strength`` (``low``).

Needs the cookbook's training package in its own environment (not a pii-guard dependency)::

    git clone --depth 1 https://github.com/fw-ai/cookbook.git
    uv venv fwvenv && VIRTUAL_ENV=fwvenv uv pip install -e cookbook/training
    FIREWORKS_API_KEY=... fwvenv/bin/python training/llm/fireworks_sft.py \\
        --file eval/generated/llm-sft/train.jsonl --run-id lab1109-v1 \\
        --out eval/generated/llm-sft/run

``--max-steps 2 --no-promote`` is a pilot (two optimiser steps, nothing kept). Metrics (loss
and gradient norm per step, token counts; never text) go to ``<out>/metrics.jsonl`` and the
final summary to ``<out>/summary.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_MODEL = "accounts/fireworks/models/muse-glimmer-30b"
TOKENIZER_MODEL = "meta-models/Muse-Glimmer-30B"
#: End of the free LoRA SFT promotion (Nov 30, Pacific; PST after Nov 1).
PROMOTION_DEADLINE = datetime(2026, 12, 1, tzinfo=timezone(timedelta(hours=-8)))
LORA_ALPHA = 32
#: Attention + MLP only. The unembedding is left frozen so vLLM can load the adapter.
LORA_TARGETS = {"train_mlp": True, "train_attn": True, "train_unembed": False}


def promotion_active(now: datetime | None = None) -> bool:
    return (now or datetime.now(UTC)) < PROMOTION_DEADLINE


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--run-id", required=True, help="names the promoted model")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lora-rank", type=int, default=8)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--learning-rate", type=float, default=1e-4)
    p.add_argument("--max-seq-len", type=int, default=4096)
    p.add_argument("--reasoning-strength", default="low")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-steps", type=int, default=None, help="stop early (pilot)")
    p.add_argument("--save-every", type=int, default=50, help="training checkpoint for resume")
    p.add_argument("--no-promote", action="store_true")
    args = p.parse_args(argv)

    if not promotion_active():
        sys.exit("The free Muse Glimmer LoRA SFT promotion has ended; training would be paid.")
    if not os.environ.get("FIREWORKS_API_KEY"):
        sys.exit("FIREWORKS_API_KEY is not set")

    from fireworks.training import sdk
    from fireworks.training.sdk import FiretitanServiceClient, FireworksClient
    from training.renderer import TrainOnWhat
    from training.renderer.muse_glimmer import MuseGlimmerOptions, MuseGlimmerRenderer
    from training.renderer.tokenizer import get_tokenizer
    from training.utils.serverless import (
        enable_serverless_supervised_409_retry,
        serverless_base_url,
    )

    tokenizer = get_tokenizer(TOKENIZER_MODEL)
    renderer = MuseGlimmerRenderer(
        tokenizer, options=MuseGlimmerOptions(reasoning_strength=args.reasoning_strength)
    )
    rows = load_rows(args.file)
    datums = []
    total_tokens = trained_tokens = 0
    for i, row in enumerate(rows):
        model_input, weights = renderer.build_supervised_example(
            row["messages"], train_on_what=TrainOnWhat.LAST_ASSISTANT_TURN
        )
        tokens = [int(t) for t in model_input.to_ints()]
        w = [float(x) for x in weights.tolist()]
        if len(tokens) > args.max_seq_len:
            sys.exit(f"row {i} has {len(tokens)} tokens > --max-seq-len {args.max_seq_len}")
        if not any(x > 0 for x in w[1:]):
            sys.exit(f"row {i} has no trained tokens")
        total_tokens += len(tokens)
        trained_tokens += int(sum(1 for x in w if x > 0))
        datums.append(
            sdk.Datum(
                model_input=sdk.ModelInput.from_ints(tokens[:-1]),
                loss_fn_inputs={"target_tokens": tokens[1:], "weights": w[1:]},
            )
        )
    print(
        f"rendered {len(datums)} rows, {total_tokens} tokens, {trained_tokens} trained", flush=True
    )

    args.out.mkdir(parents=True, exist_ok=True)
    log = (args.out / "metrics.jsonl").open("a", encoding="utf-8")
    service = FiretitanServiceClient(
        api_key=os.environ["FIREWORKS_API_KEY"],
        base_url=serverless_base_url(
            os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai")
        ),
    )
    enable_serverless_supervised_409_retry(service)
    started = time.time()
    summary: dict[str, Any] = {
        "base_model": BASE_MODEL,
        "run_id": args.run_id,
        "rows": len(datums),
        "tokens_per_epoch": total_tokens,
        "trained_tokens_per_epoch": trained_tokens,
        "hyperparameters": {
            "lora_rank": args.lora_rank,
            "lora_alpha": LORA_ALPHA,
            "lora_targets": LORA_TARGETS,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "optimizer": "adam(0.9, 0.999, eps=1e-8, wd=0, clip=1.0)",
            "loss": "cross_entropy on the assistant answer only",
            "reasoning_strength": args.reasoning_strength,
            "seed": args.seed,
        },
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        # One concurrent run per base model on the free tier; a just-closed session holds the
        # slot until it expires, so wait for it rather than fail.
        for attempt in range(60):
            try:
                client = service.create_lora_training_client(
                    base_model=BASE_MODEL, rank=args.lora_rank, alpha=LORA_ALPHA, **LORA_TARGETS
                )
                break
            except Exception as exc:
                if "RATE_LIMIT" not in str(exc) and "429" not in str(exc):
                    raise
                print(f"training slot busy, waiting (attempt {attempt + 1})", flush=True)
                time.sleep(60)
        else:
            sys.exit("no free training slot after 60 minutes")
        summary["session"] = getattr(service, "training_session_id", None)
        summary["training_run"] = getattr(client, "run_id", None)
        print(f"session={summary['session']} run={summary['training_run']}", flush=True)
        adam = sdk.AdamParams(
            learning_rate=args.learning_rate,
            beta1=0.9,
            beta2=0.999,
            eps=1e-8,
            weight_decay=0.0,
            grad_clip_norm=1.0,
        )
        rng = random.Random(args.seed)  # noqa: S311 - data order, not a secret
        step = 0
        done = False
        for epoch in range(args.epochs):
            order = list(range(len(datums)))
            rng.shuffle(order)
            for start in range(0, len(order), args.batch_size):
                batch = [datums[i] for i in order[start : start + args.batch_size]]
                fb = client.forward_backward(batch, "cross_entropy").result()
                opt = client.optim_step(adam, emit_grad_norm_metrics=True).result()
                step += 1
                metrics = dict(getattr(fb, "metrics", None) or {})
                n = metrics.get("response_tokens") or metrics.get("num_loss_tokens") or 1.0
                loss = metrics.get("loss:sum", 0.0) / max(float(n), 1.0)
                grad = {
                    k: v for k, v in (getattr(opt, "metrics", None) or {}).items() if "grad" in k
                }
                row = {
                    "step": step,
                    "epoch": epoch + 1,
                    "loss": round(loss, 5),
                    "elapsed_s": round(time.time() - started, 1),
                    **grad,
                }
                log.write(json.dumps(row) + "\n")
                log.flush()
                print(json.dumps(row), flush=True)
                if args.save_every and step % args.save_every == 0 and not args.no_promote:
                    client.save_state(f"s{step}").result()
                if args.max_steps and step >= args.max_steps:
                    done = True
                    break
            if done:
                break
        summary["steps"] = step
        summary["wall_time_s"] = round(time.time() - started, 1)
        if not args.no_promote:
            snapshot = client.save_weights_for_sampler("final").result().path
            summary["sampler_checkpoint"] = snapshot
            fw = FireworksClient(
                api_key=os.environ["FIREWORKS_API_KEY"],
                base_url=os.environ.get("FIREWORKS_BASE_URL", "https://api.fireworks.ai"),
            )
            ckpts = [
                r
                for r in fw.list_training_session_checkpoints(service.training_session_name)
                if r.get("promotable")
                and "final" in (r.get("checkpointName") or r.get("name") or "")
            ]
            if not ckpts:
                raise RuntimeError("no promotable final checkpoint")
            target = max(ckpts, key=lambda r: r.get("createTime", ""))
            model_id = f"pii-guard-glimmer-{args.run_id}"[:63].rstrip("-")
            fw.promote_session_checkpoint(
                name=target["name"], output_model_id=model_id, base_model=BASE_MODEL
            )
            summary["promoted_model"] = f"accounts/{fw.account_id}/models/{model_id}"
            print(json.dumps({"promoted_model": summary["promoted_model"]}), flush=True)
    finally:
        log.close()
        summary["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
