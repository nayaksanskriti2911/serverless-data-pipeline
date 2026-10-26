from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_athena as athena,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
)
from constructs import Construct

# AWS-managed "AWS SDK for pandas" layer (awswrangler + pandas), Python 3.12, x86_64, ap-south-1.
# For other regions/versions see: https://aws-sdk-pandas.readthedocs.io/en/stable/layers.html
SDK_PANDAS_LAYER_ARN = "arn:aws:lambda:ap-south-1:336392948345:layer:AWSSDKPandas-Python312:27"

GLUE_DATABASE = "pipeline_db"
GLUE_TABLE = "sales_curated"


class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Buckets (auto-deleted on `cdk destroy` so you are not charged for leftovers)
        raw_bucket = s3.Bucket(
            self,
            "RawBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        curated_bucket = s3.Bucket(
            self,
            "CuratedBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Lambda: validate + clean + write Parquet + register Glue table
        fn = _lambda.Function(
            self,
            "ValidateAndCurate",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_function.lambda_handler",
            code=_lambda.Code.from_asset("lambda_src"),
            memory_size=1024,
            timeout=Duration.minutes(5),
            layers=[_lambda.LayerVersion.from_layer_version_arn(self, "SdkPandasLayer", SDK_PANDAS_LAYER_ARN)],
            environment={
                "CURATED_BUCKET": curated_bucket.bucket_name,
                "KEY_COLUMNS": "order_id,total_amount",
                "REQUIRED_COLUMNS": "order_id,customer_id,order_date,category,city,payment_method,quantity,unit_price,total_amount",
                "GLUE_DATABASE": GLUE_DATABASE,
                "GLUE_TABLE": GLUE_TABLE,
            },
        )

        # Least-privilege-ish permissions
        raw_bucket.grant_read(fn)
        curated_bucket.grant_read_write(fn)
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:CreateDatabase",
                    "glue:GetTable",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:GetPartitions",
                    "glue:BatchCreatePartition",
                    "glue:CreatePartition",
                ],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:catalog",
                    f"arn:aws:glue:{self.region}:{self.account}:database/{GLUE_DATABASE}",
                    f"arn:aws:glue:{self.region}:{self.account}:table/{GLUE_DATABASE}/*",
                ],
            )
        )

        # Event-driven trigger: any new .csv in the raw bucket starts the pipeline
        raw_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(fn),
            s3.NotificationKeyFilter(suffix=".csv"),
        )

        # Athena workgroup with a results location already configured
        athena.CfnWorkGroup(
            self,
            "AthenaWorkGroup",
            name="pipeline-wg",
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{curated_bucket.bucket_name}/athena-results/"
                ),
            ),
        )

        CfnOutput(self, "RawBucketName", value=raw_bucket.bucket_name)
        CfnOutput(self, "CuratedBucketName", value=curated_bucket.bucket_name)
        CfnOutput(self, "AthenaWorkGroupName", value="pipeline-wg")
