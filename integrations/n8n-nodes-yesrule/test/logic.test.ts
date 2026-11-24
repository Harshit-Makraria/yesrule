import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildRequest, routeFor } from '../nodes/Yesrule/logic';

const base = {
	agent: 'Invoices', action: 'send_email', targetType: 'invoice', currency: 'INR', recipientKnown: true,
	reversible: false, environment: 'production', timeoutSeconds: 600, approvalsNeeded: 1,
};

test('builds a valid Yesrule request', () => {
	const r = buildRequest({ ...base, amount: 4200, recipient: 'a@b.com', client: 'acme' }, { id: 1 });
	assert.equal(r.platform, 'n8n');
	assert.deepEqual(r.amount, { value: 4200, currency: 'INR' });
	assert.deepEqual(r.recipient, { id: 'a@b.com', known: true });
	assert.equal(r.client, 'acme');
});

test('omits empty optional fields and clamps limits', () => {
	const r = buildRequest({ ...base, amount: 0, timeoutSeconds: 1, approvalsNeeded: 99 }, {});
	assert.equal(r.amount, undefined);
	assert.equal(r.recipient, undefined);
	assert.equal(r.timeout_s, 5);
	assert.equal(r.approvals_needed, 5);
});

test('routes statuses to the right output', () => {
	assert.equal(routeFor('approved'), 0);
	assert.equal(routeFor('auto_approved'), 0);
	for (const s of ['denied', 'auto_denied', 'expired', 'pending', 'flagged']) assert.equal(routeFor(s), 1);
});
