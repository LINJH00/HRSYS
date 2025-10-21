docker build -t kdd-hr-system .

docker run -d --name kdd-hr -p 8501:8501 kdd-hr-system:latest