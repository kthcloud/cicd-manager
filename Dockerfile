FROM python

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

RUN pip install -r /app/requirements.txt

EXPOSE 8000

COPY ./ /app/

ENTRYPOINT [ "python", "/app/main.py" ]
