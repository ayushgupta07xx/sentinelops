# LinkedIn launch post

**SentinelOps — an agentic LLM copilot for SRE incident response. Built solo. 5 weeks. ₹0 compute.**

It's 3 AM. An SRE gets paged. They have five minutes to start writing a postmortem.

I built SentinelOps to take that alert, retrieve runbooks and historical incidents from a vector index, query the agent's tools, and draft the postmortem with a fine-tuned 7-billion-parameter LLM. End-to-end in under three minutes.

What's inside:

→ Mistral-7B-Instruct fine-tuned with QLoRA (4-bit NF4, rank-16 LoRA) on ~2,500 real public postmortems. 21 GPU-hours across two Kaggle T4 sessions.

→ Two-stage retrieval — BGE embeddings + cross-encoder reranker over Qdrant. LangGraph agent orchestrating Prometheus, runbook search, and drafting tools.

→ Served via vLLM on Modal (AWQ-quantized). FastAPI + React UI. ~140s warm end-to-end on a single T4.

→ Production-shaped: deployed to Kubernetes via Helm + ArgoCD, Prometheus + Grafana dashboards for LLM-specific metrics, Kafka ingestion decoupling the pager path, Airflow weekly retrain gated by a Keras drift detector, Ragas eval-gate in CI.

→ Faithfulness 0.63 on a 20-case held-out set, graded by Llama-3.3-70B-as-judge. Honest model card with named failure modes — published, not hand-tuned.

Open source.

🔗 Repo: github.com/ayushgupta07xx/sentinelops
🔗 Model: huggingface.co/ayushgupta7777/sentinelops-mistral7b-awq
🔗 Demo: https://youtu.be/Yd0doUw2XG8

#MLOps #LLM #AIEngineering #SRE #MachineLearning
