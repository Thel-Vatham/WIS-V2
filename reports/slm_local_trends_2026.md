# Local Small Language Models (SLMs) — Trends & Benchmarks 2026

**Report date:** 2026-09-21
**Scope:** Phi-4, Llama 3.3, DeepSeek (R1 Distill family), plus context on Qwen3 / Gemma 3/4
**Focus:** VRAM consumption vs. performance for local inference

---

## 1. Executive Summary

In 2026 the local-SLM landscape has consolidated around **4-bit quantization (Q4_K_M / GGUF)** as the practical default for consumer hardware. The key shift is not raw parameter count but **efficiency per gigabyte of VRAM**:

- **Phi-4 (14B)** remains the strongest reasoning-per-VRAM model in the 12–16 GB class.
- **Llama 3.3 70B** is now the "big local" reference, but realistically requires 40–48 GB VRAM at Q4 — workstation/dual-GPU territory.
- **DeepSeek R1 Distill (Qwen/Llama 7B–32B)** dominates *chain-of-thought reasoning* at small sizes, at the cost of much longer outputs (tokens/sec feels slower even when raw speed is equal).
- **Qwen3 / Gemma 3–4** are the main challengers in the sub-8B edge tier.

---

## 2. VRAM vs Performance — Comparative Tables

### 2.1 Phi-4 (14B)

| Quantization | Approx. VRAM | Quality retention | Notes |
|---|---|---|---|
| FP16 | ~28–32 GB | 100% (baseline) | Needs A100 / 2× consumer GPUs |
| Q8_0 | ~16 GB | ~99% | Fits 16 GB cards (4080/4090/5070 Ti) |
| **Q4_K_M** | **~9–10 GB** | **~97%** | **Sweet spot — fits 12 GB cards** |
| Q4_0 | ~8.5 GB | ~95% | Fastest Q4 variant |

**Strengths:** math, coding, structured reasoning. **Weakness:** weaker long-context recall than Llama.

### 2.2 Llama 3.3 70B

| Quantization | Approx. VRAM | Quality retention | Notes |
|---|---|---|---|
| FP16 | ~140 GB | 100% | Multi-GPU only |
| Q8_0 | ~70 GB | ~99% | 2× 48 GB GPUs |
| **Q4_K_M** | **~40–43 GB** | **~97%** | Dual 24 GB GPU or 48 GB workstation |
| Q4_0 | ~38 GB | ~95% | Cheapest viable 70B |

**Strengths:** general knowledge, long context, instruction following. **Weakness:** VRAM cost.

### 2.3 DeepSeek R1 Distill family

| Model | Quantization | Approx. VRAM | Reasoning profile |
|---|---|---|---|
| R1-Distill-Qwen-7B | Q4_K_M | ~5–6 GB | Fast CoT, fits 8 GB cards |
| R1-Distill-Llama-8B | Q4_K_M | ~6 GB | Strong math for size |
| R1-Distill-Qwen-14B | Q4_K_M | ~9–10 GB | Best reasoning/VRAM ratio |
| R1-Distill-Qwen-32B | Q4_K_M | ~19–20 GB | Near-70B reasoning, 24 GB card |
| R1-Distill-Llama-70B | Q4_K_M | ~40–43 GB | Full R1 reasoning locally |

**Caveat:** R1-style models emit long "thinking" traces → effective *perceived* throughput is lower even at equal tokens/sec.

### 2.4 Cross-model VRAM efficiency snapshot

| Model | Params | Q4 VRAM | Tier | Best for |
|---|---|---|---|---|
| Phi-4 | 14B | ~9–10 GB | 12 GB GPU | Reasoning, code, math |
| Llama 3.3 | 70B | ~40–43 GB | Workstation | General + long context |
| DeepSeek R1-Distill-Qwen | 14B | ~9–10 GB | 12 GB GPU | Chain-of-thought reasoning |
| DeepSeek R1-Distill-Qwen | 32B | ~19–20 GB | 24 GB GPU | Deep reasoning |
| Qwen3 | 4B | ~3 GB | 6–8 GB GPU | Edge / on-device |
| Gemma 3 | 4B | ~3 GB | 6–8 GB GPU | Edge / multilingual |

---

## 3. Key 2026 Trends

1. **Q4 is the new default** — quality loss (~3%) is negligible vs. 4× VRAM savings.
2. **Reasoning models changed the metric** — tokens/sec is no longer enough; *useful tokens per second* (accounting for CoT overhead) matters.
3. **The 12 GB tier is the sweet spot** — Phi-4 14B and DeepSeek-14B both land there.
4. **70B is workstation-only** — still not consumer-viable at usable quality.
5. **Edge models (3–4B) matured** — Qwen3-4B and Gemma 3-4B now handle real assistant tasks.
6. **Gemma 4 (Apache 2.0)** — Google's license switch (announced 2026) removed a major adoption barrier.

---

## 4. Hardware Recommendations

| Budget / GPU | Best model choice |
|---|---|
| 8 GB VRAM | DeepSeek R1-Distill-7B/8B (Q4) |
| 12 GB VRAM | **Phi-4 14B (Q4)** or DeepSeek-R1-14B |
| 16 GB VRAM | Phi-4 (Q8) or DeepSeek-R1-14B (Q8) |
| 24 GB VRAM | DeepSeek R1-Distill-32B (Q4) |
| 48 GB+ / dual GPU | Llama 3.3 70B (Q4) |

---

## 5. Methodology & Sources

Data aggregated from public benchmark pages and hardware guides:
- localai.computer — Microsoft Phi-4 VRAM/GPU requirements
- macmyths.com — Phi-4 local performance review (2026)
- llmhardware.io — Llama 3.1/3.3 hardware requirements
- insiderllm.com — Llama 3 full size guide (2026)
- tinyweights.dev — Best Small Language Models 2026
- awesomeagents.ai — Small Language Model Leaderboard (<10B)
- aiportalx.com — Best Small & Edge LLMs 2026
- Wikipedia — List of large language models (2026)

> **Note:** VRAM figures are approximate and vary with context length, KV-cache size, and runtime (llama.cpp / Ollama / vLLM). Treat as planning estimates, not exact measurements.
