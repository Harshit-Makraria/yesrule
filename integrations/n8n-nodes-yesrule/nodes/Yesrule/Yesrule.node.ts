import type {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';
import { NodeOperationError } from 'n8n-workflow';
import { buildRequest, FINAL, routeFor, type NodeParams } from './logic';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class Yesrule implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Yesrule Approval',
		name: 'yesrule',
		icon: 'fa:user-check',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["action"]}}',
		description: 'Wait for approval (from a person or a learned rule) before continuing',
		defaults: { name: 'Yesrule Approval' },
		inputs: ['main'],
		outputs: ['main', 'main'],
		outputNames: ['Approved', 'Denied'],
		credentials: [{ name: 'yesruleApi', required: true }],
		properties: [
			{ displayName: 'Action', name: 'action', type: 'string', default: 'send_email', required: true },
			{ displayName: 'Agent Name', name: 'agent', type: 'string', default: '={{$workflow.name}}' },
			{ displayName: 'Summary', name: 'summary', type: 'string', default: '' },
			{ displayName: 'Target Type', name: 'targetType', type: 'string', default: 'unknown' },
			{ displayName: 'Amount', name: 'amount', type: 'number', default: 0 },
			{ displayName: 'Currency', name: 'currency', type: 'string', default: 'INR' },
			{ displayName: 'Recipient', name: 'recipient', type: 'string', default: '' },
			{ displayName: 'Recipient Is Known', name: 'recipientKnown', type: 'boolean', default: false },
			{ displayName: 'Reversible', name: 'reversible', type: 'boolean', default: true },
			{
				displayName: 'Environment', name: 'environment', type: 'options', default: 'production',
				options: ['production', 'staging', 'development', 'unknown'].map((v) => ({ name: v, value: v })),
			},
			{ displayName: 'Client', name: 'client', type: 'string', default: '' },
			{ displayName: 'Timeout (Seconds)', name: 'timeoutSeconds', type: 'number', default: 600 },
			{ displayName: 'Approvals Needed', name: 'approvalsNeeded', type: 'number', default: 1 },
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const { baseUrl } = (await this.getCredentials('yesruleApi')) as { baseUrl: string };
		const out: INodeExecutionData[][] = [[], []];

		for (let i = 0; i < items.length; i++) {
			const p = {} as NodeParams;
			for (const key of ['agent', 'action', 'targetType', 'amount', 'currency', 'recipient', 'recipientKnown',
				'reversible', 'environment', 'client', 'summary', 'timeoutSeconds', 'approvalsNeeded']) {
				(p as unknown as Record<string, unknown>)[key] = this.getNodeParameter(key, i);
			}
			const body = buildRequest(p, items[i].json);
			let res = (await this.helpers.httpRequest({
				method: 'POST', url: `${baseUrl}/v1/requests`, body, json: true,
			})) as { id: string; status: string; reason: string; receipt?: unknown };
			const deadline = Date.now() + p.timeoutSeconds * 1000 + 5000;
			while (!FINAL.has(res.status) && Date.now() < deadline) {
				await sleep(2000);
				res = (await this.helpers.httpRequest({
					method: 'GET', url: `${baseUrl}/v1/requests/${res.id}`, json: true,
				})) as typeof res;
			}
			if (!res.id) throw new NodeOperationError(this.getNode(), 'Yesrule returned no request id');
			out[routeFor(res.status)].push({
				json: { ...items[i].json, yesrule: { id: res.id, status: res.status, reason: res.reason, receipt: res.receipt } },
				pairedItem: { item: i },
			});
		}
		return out;
	}
}
