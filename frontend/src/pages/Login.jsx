import { useState } from 'react';
import { BannerSlim, Box, Button, Flex, Heading, Link, Text, TextField } from 'gestalt';
import { logIn } from '../api/client.js';

// The one page a person can reach without a session (M1). Plain fields and
// one primary button, per the design system record: no new visual language
// and no component this app did not already use.
//
// It carries no navigation, because every link in the nav would bounce
// straight back here, and it shows one message for every failed attempt,
// so it cannot be used to find out who has an account.
export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await logIn(email, password);
      // A full page load, not a client-side route change: the board is
      // behind the gate, so the request that fetches it has to carry the
      // cookie the sign-in just set.
      window.location.assign(result?.next || '/jobs');
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Box padding={6} display="flex" justifyContent="center">
      <Box maxWidth={360} width="100%">
        <form onSubmit={submit}>
          <Flex direction="column" gap={4}>
            <Heading size="500" accessibilityLevel={1}>
              Log in
            </Heading>
            <Text color="subtle">CareerOS is invitation only. Ask the owner for an account.</Text>
            {error ? <BannerSlim type="error" message={error} /> : null}
            <TextField
              id="login-email"
              type="email"
              label="Email"
              autoComplete="username"
              value={email}
              onChange={({ value }) => setEmail(value)}
            />
            <TextField
              id="login-password"
              type="password"
              label="Password"
              autoComplete="current-password"
              value={password}
              onChange={({ value }) => setPassword(value)}
            />
            <Button type="submit" color="red" text="Log in" disabled={busy} fullWidth />
            {/* CAREER-97: the mailed-link pages (forgot password, invites,
                reset) are deliberately server-rendered, not React routes,
                so this is a plain same-origin anchor that does a full page
                load into /forgot-password — mirroring the Jinja fallback
                login page, which has carried this link since it shipped. */}
            <Flex justifyContent="center">
              <Link href="/forgot-password" display="inlineBlock">
                <Text size="200" color="subtle">Forgot password?</Text>
              </Link>
            </Flex>
          </Flex>
        </form>
      </Box>
    </Box>
  );
}
