FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput
EXPOSE 3000
# The database is only reachable at run time. load_sources re-applies the data gates on every start.
# waitress sets no request time limit, so a step that waits minutes on the model is not cut off here.
CMD python manage.py migrate --noinput && python manage.py load_sources && \
    exec waitress-serve --listen=0.0.0.0:${PORT:-3000} --threads=16 --trusted-proxy='*' --trusted-proxy-headers=x-forwarded-proto server.wsgi:application
