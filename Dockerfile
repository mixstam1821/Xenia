FROM python:3.12-slim
 
WORKDIR /app/backend
 
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r /app/requirements.txt
 
COPY . /app/
 
RUN chmod -R 777 /app/backend
 
EXPOSE 8994
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8994"]
