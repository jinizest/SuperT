FROM python:3.7.3

ENV LANG C.UTF-8

# Copy data for add-on
COPY run.sh makeconf.sh app.py /
COPY templates /templates

# Install requirements for add-on
RUN python3 -m pip install Flask==2.0.1
RUN python3 -m pip install requests
RUN python3 -m pip install SRTrain
RUN python3 -m pip install urllib3==1.26.15

# 작업 디렉토리 설정
WORKDIR /share

# 실행 권한 부여
RUN chmod a+x /run.sh

# 실행 명령 설정
CMD [ "/run.sh" ]