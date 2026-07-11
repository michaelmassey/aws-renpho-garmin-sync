import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';

export class AwsRenphoGarminSyncStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // 1. DynamoDB Table with partition key "id"
    const table = new dynamodb.Table(this, 'WeightSyncTable', {
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // Safeguard config or DESTROY for simple personal use
    });

    // 2. Reference names for the pre-existing SSM Parameter Store SecureString parameters
    const paramNames = {
      renphoEmail: '/renpho-garmin-sync/renpho_email',
      renphoPassword: '/renpho-garmin-sync/renpho_password',
      garminEmail: '/renpho-garmin-sync/garmin_email',
      garminPassword: '/renpho-garmin-sync/garmin_password',
    };

    // 3. Define the Lambda PythonFunction
    const syncFunction = new PythonFunction(this, 'RenphoGarminSyncFunction', {
      entry: 'lambda', // point to the lambda directory
      runtime: lambda.Runtime.PYTHON_3_11,
      index: 'index.py',
      handler: 'handler',
      timeout: cdk.Duration.minutes(10), // Sync tasks might take a few minutes
      environment: {
        TABLE_NAME: table.tableName,
        RENPHO_EMAIL_PARAM_NAME: paramNames.renphoEmail,
        RENPHO_PASSWORD_PARAM_NAME: paramNames.renphoPassword,
        GARMIN_EMAIL_PARAM_NAME: paramNames.garminEmail,
        GARMIN_PASSWORD_PARAM_NAME: paramNames.garminPassword,
        BATCH_LIMIT: '1', // Default to 1 for safety, configurable via AWS Console or CDK Stack
      },
    });

    // Grant Lambda permission to read/write to the DynamoDB table
    table.grantReadWriteData(syncFunction);

    // Grant Lambda permission to read the pre-existing SSM SecureString parameters
    for (const [idKey, paramName] of Object.entries(paramNames)) {
      const param = ssm.StringParameter.fromSecureStringParameterAttributes(this, `Imported-${idKey}`, {
        parameterName: paramName,
      });
      param.grantRead(syncFunction);
    }

    // 4. EventBridge Cron Schedule to run the Lambda once per day (00:00 UTC)
    const dailyRule = new events.Rule(this, 'DailySyncRule', {
      schedule: events.Schedule.cron({ minute: '0', hour: '0' }),
    });

    dailyRule.addTarget(new targets.LambdaFunction(syncFunction));
  }
}

