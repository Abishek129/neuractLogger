/**
 * NDJSON stream parser — async generator that handles chunked TCP delivery.
 * Yields parsed JSON objects one at a time from an HTTP streaming response.
 */
export async function* parseNDJSON(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete last line
            for (const line of lines) {
                if (line.trim()) {
                    try {
                        yield JSON.parse(line);
                    } catch (e) {
                        console.warn('NDJSON parse error:', e, 'line:', line);
                    }
                }
            }
        }
        // Flush remaining buffer
        if (buffer.trim()) {
            try {
                yield JSON.parse(buffer);
            } catch (e) {
                console.warn('NDJSON final parse error:', e);
            }
        }
    } finally {
        reader.releaseLock();
    }
}
