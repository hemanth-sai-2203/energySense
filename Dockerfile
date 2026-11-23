# EnergySense India — Production Container
FROM python:3.12-slim

WORKDIR /app

# Ensure standard library stdout/stderr is flushed immediately
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV HOST=0.0.0.0

# Copy all application files
COPY . .

# Expose container port (overridden dynamically by cloud platforms via $PORT)
EXPOSE 8000

# Zero-dependency multithreaded Python server
CMD ["python", "server.py"]

