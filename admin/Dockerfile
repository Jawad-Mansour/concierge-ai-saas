# Owner: Charbel

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV && \
    uv pip install --python $VIRTUAL_ENV/bin/python --no-cache \
    streamlit hvac requests

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", \
    "--server.address=0.0.0.0", \
    "--server.port=8501"]
