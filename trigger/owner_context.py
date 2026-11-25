"""Assemble one owner conversation under a single byte budget."""
import json

MAX_TOTAL_BYTES = 16 * 1024
NOTE_RESERVE = 256
OMISSION_NOTE = ('本轮上下文超过字节预算，已省略 {} 项低优先级内容；'
                 '不要声称看过省略的对话或资料。')


def _size(messages):
    return len(json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode())


def _key(message):
    return (message.get('role'), message.get('content'))


def assemble(base=(), memory=(), knowledge=(), history=(), max_bytes=MAX_TOTAL_BYTES):
    if not isinstance(max_bytes, int) or max_bytes <= NOTE_RESERVE:
        raise ValueError('context byte budget must exceed the note reserve')
    chosen, seen, omitted = [], set(), 0
    limit = max_bytes - NOTE_RESERVE

    # Identity and explicit group context are required; keep them even if over budget.
    for message in base:
        key = _key(message)
        if key not in seen:
            seen.add(key)
            chosen.append(message)

    def add_unit(messages):
        nonlocal omitted
        messages = list(messages)
        keys = [_key(message) for message in messages]
        if (not messages or any(key in seen for key in keys)
                or len(set(keys)) != len(keys)):
            return
        if _size(chosen + messages) > limit:
            omitted += len(messages)
            return
        seen.update(keys)
        chosen.extend(messages)

    add_unit(memory)
    add_unit(knowledge)

    kept = []
    for message in reversed(list(history)):
        key = _key(message)
        if key in seen or any(_key(item) == key for item in kept):
            continue
        if _size(chosen + kept + [message]) > limit:
            omitted += 1
            continue
        kept.append(message)
    chosen.extend(reversed(kept))

    if omitted:
        chosen.append({'role': 'system', 'content': OMISSION_NOTE.format(omitted)})
    return chosen