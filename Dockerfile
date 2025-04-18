# Dockerfile for saloonbot's Discord bot.

FROM python:3.13-slim
ARG GIT_SHA

# Use a non-root user to avoid warnings about
# running pip as root.
RUN adduser --gecos "" --disabled-password appuser
WORKDIR /app
RUN echo $GIT_SHA > .version
USER appuser

# Add ~/.local/bin to PATH to avoid Python
# package warnings.
ENV PATH="/home/appuser/.local/bin:$PATH"

RUN pip install -U pip
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser . .

CMD ["python", "bot.py"]
