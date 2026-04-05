# AWS Lambda container image for lambdas/get_study_assignment/handler.py
# Build from repo root (linux/amd64 matches default x86_64 Lambda; use buildx on Apple Silicon):
#   docker buildx build --platform linux/amd64 --load \
#     -f Dockerfiles/lambda_get_study_assignment.Dockerfile -t get-study-assignment:local .

FROM public.ecr.aws/lambda/python:3.12

RUN pip install --no-cache-dir \
    "boto3>=1.34.0" \
    "botocore>=1.34.0" \
    "numpy>=2.0.0" \
    "pandas>=3.0.2" \
    "pydantic>=2.0.0"

COPY lambdas ${LAMBDA_TASK_ROOT}/lambdas
COPY lib ${LAMBDA_TASK_ROOT}/lib
COPY jobs ${LAMBDA_TASK_ROOT}/jobs

CMD [ "lambdas.get_study_assignment.handler.handler" ]
