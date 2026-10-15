import { useEffect, useState } from 'react';

// One width decides the phone layout, the way MOBILE_BREAKPOINT does for the
// Jinja theme: the D7 board brief draws one column at a time below 720px, so
// every rule that follows from that reads this constant rather than
// repeating the number.
export const PHONE_MAX_WIDTH = 719;

const PHONE_QUERY = `(max-width: ${PHONE_MAX_WIDTH}px)`;

// True while the viewport is phone-width. A media query rather than a resize
// listener on window.innerWidth, so the browser decides when the layout
// changes and the two cannot disagree; the first value is read synchronously
// so the first paint is already the right layout.
export function usePhoneLayout() {
  const [isPhone, setIsPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches);

  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY);
    const update = () => setIsPhone(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return isPhone;
}
