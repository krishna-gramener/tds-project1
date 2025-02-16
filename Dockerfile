# Use an official Python image
FROM python:3.9

# Set the working directory
WORKDIR /app

# Copy the project files
COPY . .

# Install dependenciess
RUN pip install fastapi uvicorn openai python-multipart requests python-dotenv

# Expose port 8000
EXPOSE 8000

# Start the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
