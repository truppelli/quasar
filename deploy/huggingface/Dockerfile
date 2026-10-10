# QUASAR's 3D map + planner on a Hugging Face Space (Docker SDK). The Space holds only this file and README.md:
# it builds from the public GitHub repo, so "Factory rebuild" on the Space picks up the latest main.
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy
ARG REF=main
ADD https://github.com/truppelli/quasar/archive/refs/heads/${REF}.tar.gz /tmp/quasar.tgz
WORKDIR /app
# Spaces run as uid 1000: serve.py's self-check and feedback.jsonl write here (lost on restart, fine for a demo)
RUN tar xzf /tmp/quasar.tgz --strip-components=1 && rm /tmp/quasar.tgz && chmod -R a+w /app
ENV HOST=0.0.0.0
EXPOSE 7860
CMD ["python", "serve.py", "7860"]
