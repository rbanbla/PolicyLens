import json
from io import BytesIO
from unittest.mock import patch
from django.test import SimpleTestCase
from ..integrations import transport


class ProviderTransportTests(SimpleTestCase):
    @patch('server.integrations.transport.provider', return_value=('https://provider.example/v1', 'chat_completions'))
    @patch('server.integrations.transport.urlopen')
    def test_chat_schema_and_normalized_response(self, open_url, provider):
        open_url.return_value = BytesIO(json.dumps({'id':'chat-test','choices':[{'finish_reason':'stop','message':{'content':'{"items": []}'}}], 'usage':{'total_tokens':10}}).encode())
        result=transport.call({'model':'model-test','instructions':'rules','input':'document','max_output_tokens':50,
            'text':{'format':{'name':'test','strict':True,'schema':{'type':'object'}}}}, 'fake-test-key')
        request=open_url.call_args.args[0]
        body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://provider.example/v1/chat/completions')
        self.assertEqual(body['messages'],[{'role':'system','content':'rules'},{'role':'user','content':'document'}])
        self.assertTrue(body['response_format']['json_schema']['strict'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['output'][0]['content'][0]['text'],'{"items": []}')

    @patch('server.integrations.transport.provider', return_value=('https://provider.example/v1','chat_completions'))
    @patch('server.integrations.transport.urlopen')
    def test_truncation_is_not_a_complete_result(self, open_url, provider):
        open_url.return_value=BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':'{"items":'}}]}).encode())
        result=transport.call({'model':'model-test','instructions':'rules','input':'doc','max_output_tokens':50,
            'text':{'format':{'name':'test','strict':True,'schema':{'type':'object'}}}},'fake-test-key')
        self.assertEqual(result['status'],'incomplete')
