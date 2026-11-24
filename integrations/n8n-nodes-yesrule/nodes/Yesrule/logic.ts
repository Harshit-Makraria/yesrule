// Pure helpers, kept separate so they can be unit tested without n8n.

export interface NodeParams {
	agent: string;
	action: string;
	targetType: string;
	amount?: number;
	currency: string;
	recipient?: string;
	recipientKnown: boolean;
	reversible: boolean;
	environment: string;
	client?: string;
	summary?: string;
	timeoutSeconds: number;
	approvalsNeeded: number;
}

export const FINAL = new Set(['approved', 'auto_approved', 'denied', 'auto_denied', 'expired', 'flagged']);
export const APPROVED = new Set(['approved', 'auto_approved']);

export function buildRequest(p: NodeParams, item: Record<string, unknown>): Record<string, unknown> {
	const req: Record<string, unknown> = {
		agent: p.agent || 'n8n-workflow',
		platform: 'n8n',
		action: p.action,
		target: { type: p.targetType || 'unknown' },
		reversible: p.reversible,
		environment: p.environment,
		timeout_s: Math.max(5, Math.min(86400, Math.round(p.timeoutSeconds))),
		approvals_needed: Math.max(1, Math.min(5, Math.round(p.approvalsNeeded || 1))),
		context: { summary: p.summary ?? '', item: JSON.stringify(item).slice(0, 2000) },
	};
	if (p.client) req.client = p.client;
	if (typeof p.amount === 'number' && p.amount > 0) req.amount = { value: p.amount, currency: p.currency || 'INR' };
	if (p.recipient) req.recipient = { id: p.recipient, known: p.recipientKnown };
	return req;
}

/** Which output an item goes to: 0 = approved, 1 = denied / expired. */
export function routeFor(status: string): 0 | 1 {
	return APPROVED.has(status) ? 0 : 1;
}
