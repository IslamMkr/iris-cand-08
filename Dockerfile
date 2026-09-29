FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml .
COPY iris ./iris
COPY fixtures ./fixtures
COPY tests ./tests
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "-m", "pytest", "-v", "-s", "-p", "no:cacheprovider"]
