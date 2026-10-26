import os

import aws_cdk as cdk

from infra.pipeline_stack import PipelineStack

app = cdk.App()
PipelineStack(
    app,
    "ServerlessDataPipeline",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="ap-south-1",  # Mumbai. The managed pandas layer ARN in the stack is for this region.
    ),
)
app.synth()
