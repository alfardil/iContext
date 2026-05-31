set shell := ["bash", "-uc"]

# run kafka, ngrok, and connect to postgres
docker *args:
    docker compose --profile public up
