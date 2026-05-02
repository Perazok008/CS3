docker build -t perazok/wpi_cs3_backend:latest -f backend.dockerfile ../..
docker build -t perazok/wpi_cs3_frontend:latest -f frontend.dockerfile ../..
docker push perazok/wpi_cs3_backend:latest
docker push perazok/wpi_cs3_frontend:latest