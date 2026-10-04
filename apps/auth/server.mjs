import Provider from 'oidc-provider';

// Local test identities only. This provider cannot bind to a network interface.
// Production uses an independently configured OIDC provider with real accounts.
const issuer = process.env.LOCAL_OIDC_ISSUER || 'http://localhost:8081';
const appBase = process.env.LOCAL_APP_BASE_URL || 'http://localhost:8080';
if (!['localhost', '127.0.0.1'].includes(new URL(issuer).hostname)) {
  throw new Error('The synthetic identity provider is restricted to loopback');
}
const provider = new Provider(issuer, {
  clients: [{client_id: 'kontroferta-local', redirect_uris: [appBase + '/api/auth/callback'],
    response_types: ['code'], grant_types: ['authorization_code'], token_endpoint_auth_method: 'none'}],
  pkce: {required: () => true},
  claims: {openid: ['sub'], profile: ['name'], email: ['email']},
  features: {devInteractions: {enabled: true}},
  async findAccount(_ctx, id) {
    return {accountId: id, async claims() {return {sub: id, name: id, email: `${id.replace(/[^a-zA-Z0-9]/g,'').toLowerCase()}@example.test`};}};
  },
});
provider.on('server_error', (_ctx, err) => console.error('identity_error', err.name));
const bind = process.env.LOCAL_OIDC_CONTAINER === 'true' ? '0.0.0.0' : '127.0.0.1';
provider.listen(new URL(issuer).port, bind, () => console.log(`Synthetic local OIDC: ${issuer}`));
