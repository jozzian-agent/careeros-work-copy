// The count a screen reader hears beside a column, a lane or a group name,
// and the one pluralisation rule every board string shares. One job is one
// job: an announced "1 jobs" is the kind of detail that only shows up when
// somebody actually listens to the page.
export function countWord(count, noun) {
  return `${count} ${count === 1 ? noun : `${noun}s`}`;
}

export function jobCount(count) {
  return countWord(count, 'job');
}
