import base64
import logging
import json
import datetime
from oauth2client.client import GoogleCredentials
from apiclient import discovery

billingID = "000000-AAAAAA-BBBBBB" #replace with the correct billing project
billing_account = "billingAccounts/" + billingID

def handle_notification(event, context):
    """Triggered from a message on a Cloud Pub/Sub topic.
    Args:
         event (dict): Event payload.
         context (google.cloud.functions.Context): Metadata for the event.
    """
    pubsub_message = base64.b64decode(event['data']).decode('utf-8')
    logging.info('Project change information: {}'.format(pubsub_message))
    project_data = json.loads(pubsub_message)['asset']['resource']['data'] #All data of interest is within the pubsub_message['asset']['resource']['data'] branch
    createdTime = project_data['createTime']
    lifecycleState = project_data['lifecycleState']
    projectID = project_data['projectId']
    projectNumber = project_data['projectNumber']
    projectName = project_data['name']

    try: #if the project has a budget-id label, then it has already run through this function before
        budgetLabel = project_data['labels']['budget-id']
        logging.info('Existing budgetID: {}'.format(budgetLabel))
        hasBudgetLabel = True
    except: #if there isn't a budget-id label, an error will be thrown
        hasBudgetLabel = False
        pass
    
    #The project hasn't been through this function before -- otherwise there is the potential for an infinite loop
    if lifecycleState == "ACTIVE" and hasBudgetLabel == False: #ACTIVE checks that the project isn't in DELETE_REQUESTED state
        # Creating credentials to be used for authentication, by using the Application Default Credentials
        # for the Cloud Function runtime environment
        credentials = GoogleCredentials.get_application_default()

        # Using Python Google API Client Library to construct a Resource object for interacting with an API
        # The name and the version of the API to use can be found here https://developers.google.com/api-client-library/python/apis/
        billing_service = discovery.build('cloudbilling', 'v1', credentials=credentials, cache_discovery=False)
        budget_service = discovery.build('billingbudgets', 'v1beta1', credentials=credentials, cache_discovery=False)   
        crm_service = discovery.build('cloudresourcemanager', 'v1', credentials=credentials, cache_discovery=False)
        
        #Ensure the correct billing account is assigned
        billing_info = billing_service.projects().updateBillingInfo(
            name='projects/{}'.format(projectID),
            body={"billingAccountName":billing_account}
        ).execute()     
        
        #Create a budget for the project
        budget_info = budget_service.billingAccounts().budgets().create(
            parent=billing_account,
            body={
                "budget": {
                    "displayName": "budget-" + projectID,
                    "budgetFilter": {
                        "projects": ["projects/" + projectNumber]
                    },
                    "amount": {
                        "specifiedAmount": {
                            "currencyCode": "USD",
                            "units": "30"
                        }
                    },
                    "allUpdatesRule": {
                        "pubsubTopic": "projects/**project_name_goes_here**/topics/**pubsub_topic_goes_here**",
                        "schemaVersion": "1.0"
                    },
                }
            }
        ).execute()
        logging.info('budgetInfo: {}'.format(budget_info))
        
        #Extract the newly created Budget ID
        budget_name = budget_info['name']
        budgetID = budget_name[budget_name.find("budgets/") + 8: len(budget_name)]
        #logging.info('budgetLabel: {}'.format(budgetID))

        #Put tags on the project (NOTE: this change will trigger any asset feed that is monitoring this project)
        #Tip: Labels must be all lowercase and dash and underscore are the only symbols allowed
        project = crm_service.projects().get(projectId=projectNumber).execute() #Get the project of interest
        project['labels'] = {
            'component': 'sandbox',
            'env': 'sandbox',
            'projectid': 'abc0123', 
            'team': 'development',
            'project-id': '{}'.format(projectID),
            'budget-id': '{}'.format(budgetID)
        }
        
        #Update the project of interest to include tags
        project = crm_service.projects().update(projectId=projectNumber,body=project).execute()
        logging.info('updatedProject: {}'.format(project))
    elif lifecycleState == "DELETE_REQUESTED" and hasBudgetLabel == True:
        # Creating credentials to be used for authentication, by using the Application Default Credentials
        # for the Cloud Function runtime environment
        credentials = GoogleCredentials.get_application_default()

        # Using Python Google API Client Library to construct a Resource object for interacting with an API
        # The name and the version of the API to use can be found here https://developers.google.com/api-client-library/python/apis/
        budget_service = discovery.build('billingbudgets', 'v1beta1', credentials=credentials, cache_discovery=False)   
        crm_service = discovery.build('cloudresourcemanager', 'v1', credentials=credentials, cache_discovery=False)    
        
        #Delete the budget for the project
        fullBudgetName = billing_account + "/budgets/" + budgetLabel
        budget_info = budget_service.billingAccounts().budgets().delete(
            name=fullBudgetName
        ).execute()

        ''' -- Cannot update tags on projects waiting for deletion
        #Remove tags on the project (NOTE: this change will trigger any asset feed that is monitoring this project)
        project = crm_service.projects().get(projectId=projectNumber).execute() #Get the project of interest
        project['labels'] = {
            'project-id': '{}'.format(projectID)
        }

        
        #Update the project of interest to delete any existing tags
        project = crm_service.projects().update(projectId=projectNumber,body=project).execute()
        logging.info('updatedProject: {}'.format(project))
        '''
