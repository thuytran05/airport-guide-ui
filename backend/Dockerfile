# Dockerfile cho Airport Guide Backend chạy trên Ubuntu 22 với ROS 2 Jazzy
FROM ros:jazzy-ros-base

# Đặt thư mục làm việc
WORKDIR /app

# Cài đặt Python, pip và các thư viện ROS 2 messages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    ros-jazzy-geometry-msgs \
    ros-jazzy-sensor-msgs \
    ros-jazzy-nav-msgs \
    ros-jazzy-nav2-msgs \
    ros-jazzy-tf2-ros \
    && rm -rf /var/lib/apt/lists/*

# Cai dat Python virtual environment
# Cho phep truy cap thu vien ROS 2 cua he thong
COPY requirements.txt /app/

RUN python3 -m venv --system-site-packages /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy mã nguồn backend
COPY . /app/

# Biến môi trường mặc định
ENV ROBOT_ADAPTER_MODE=ros
ENV ROS_DOMAIN_ID=0
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Khởi chạy backend với môi trường ROS 2 Jazzy đã source sẵn
CMD ["/bin/bash", "-c", "source /opt/ros/jazzy/setup.bash && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
