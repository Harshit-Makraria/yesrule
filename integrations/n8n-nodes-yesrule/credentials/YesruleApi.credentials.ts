import type { ICredentialType, INodeProperties } from 'n8n-workflow';

export class YesruleApi implements ICredentialType {
	name = 'yesruleApi';
	displayName = 'Yesrule API';
	documentationUrl = 'https://github.com/harshitmakraria/yesrule';
	properties: INodeProperties[] = [
		{ displayName: 'Base URL', name: 'baseUrl', type: 'string', default: 'http://localhost:8787' },
	];
}
