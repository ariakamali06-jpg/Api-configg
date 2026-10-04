FROM python:3.11-slim

WORKDIR /app

# The bot uses only Python standard library modules (zero external pip packages needed)
COPY bot.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
