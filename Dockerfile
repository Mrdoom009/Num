# Use the latest Python 3.12 slim image
FROM python:3.12-slim

# Set the working directory
WORKDIR /bot

# Install system dependencies needed for tgcrypto
RUN apt-get update && apt-get install -y gcc python3-dev

# Copy the main bot file and requirements file into the container
COPY . .

# Install required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 8000 for the Flask health check endpoint
EXPOSE 8000

# Set the default command to run the bot
CMD ["python", "nidhi.py"]
