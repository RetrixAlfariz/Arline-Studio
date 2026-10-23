//! Structural text chunking compatible with the Python memory indexer.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChunkUnit {
    pub text: String,
    pub start_id: String,
    pub end_id: String,
    pub ordinal: usize,
}

fn chars_len(s: &str) -> usize {
    s.chars().count()
}

fn suffix_chars(s: &str, count: usize) -> String {
    if count == 0 {
        return String::new();
    }
    let all: Vec<char> = s.chars().collect();
    all[all.len().saturating_sub(count)..].iter().collect()
}

fn sentences(block: &str, max_chars: usize) -> Vec<String> {
    if chars_len(block) <= max_chars {
        return vec![block.to_owned()];
    }
    let chars: Vec<char> = block.chars().collect();
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        if matches!(chars[i], '.' | '!' | '?')
            && i + 1 < chars.len()
            && chars[i + 1].is_whitespace()
        {
            let body: String = chars[start..=i].iter().collect();
            if !body.trim().is_empty() {
                out.push(body.trim().to_owned());
            }
            i += 1;
            while i < chars.len() && chars[i].is_whitespace() {
                i += 1;
            }
            start = i;
            continue;
        }
        i += 1;
    }
    let tail: String = chars[start..].iter().collect();
    if !tail.trim().is_empty() {
        out.push(tail.trim().to_owned());
    }
    if out.is_empty() {
        vec![block.to_owned()]
    } else {
        out
    }
}

/// Split text at paragraph/sentence boundaries. A single sentence longer than
/// `max_chars` intentionally remains oversized, matching Python behavior.
pub fn chunk(
    text: &str,
    source_id: &str,
    max_chars: usize,
    overlap_chars: usize,
) -> Vec<ChunkUnit> {
    let normalized = text.replace("\r\n", "\n").trim().to_owned();
    if normalized.is_empty() {
        return Vec::new();
    }
    let mut blocks = Vec::new();
    let mut paragraph = Vec::new();
    for line in normalized.lines() {
        if line.trim().is_empty() {
            if !paragraph.is_empty() {
                blocks.push(paragraph.join("\n").trim().to_owned());
                paragraph.clear();
            }
        } else {
            paragraph.push(line.to_owned());
        }
    }
    if !paragraph.is_empty() {
        blocks.push(paragraph.join("\n").trim().to_owned());
    }
    let blocks = if blocks.is_empty() {
        vec![normalized]
    } else {
        blocks
    };
    let max_chars = max_chars.max(400);
    let overlap_chars = overlap_chars.min(max_chars / 3);
    let mut output = Vec::new();
    let mut current: Vec<String> = Vec::new();
    let mut current_chars = 0usize;
    for block in blocks {
        for sentence in sentences(&block, max_chars) {
            let projected =
                current_chars + chars_len(&sentence) + if current.is_empty() { 0 } else { 2 };
            if !current.is_empty() && projected > max_chars {
                let body = current.join("\n\n").trim().to_owned();
                let ordinal = output.len();
                output.push(ChunkUnit {
                    text: body.clone(),
                    start_id: format!("{source_id}:block:{ordinal}"),
                    end_id: format!("{source_id}:block:{ordinal}"),
                    ordinal,
                });
                let overlap = suffix_chars(&body, overlap_chars).trim().to_owned();
                current = if overlap.is_empty() {
                    Vec::new()
                } else {
                    vec![overlap.clone()]
                };
                current_chars = chars_len(&overlap);
            }
            current_chars += chars_len(&sentence) + if !current.is_empty() { 2 } else { 0 };
            current.push(sentence);
        }
    }
    if !current.is_empty() {
        let body = current.join("\n\n").trim().to_owned();
        let ordinal = output.len();
        output.push(ChunkUnit {
            text: body.clone(),
            start_id: format!("{source_id}:block:{ordinal}"),
            end_id: format!("{source_id}:block:{ordinal}"),
            ordinal,
        });
    }
    output
}

#[cfg(test)]
mod tests {
    use super::chunk;

    #[test]
    fn normalizes_unicode_crlf_and_empty_input() {
        assert!(chunk(" \r\n\r\n ", "x", 400, 10).is_empty());
        let result = chunk("Ångström\r\n\r\n第二段", "doc", 400, 0);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].start_id, "doc:block:0");
        assert_eq!(result[0].text, "Ångström\n\n第二段");
    }

    #[test]
    fn long_blocks_split_sentences_and_preserve_oversized_sentence() {
        let result = chunk("One. Two. Three.", "s", 400, 0);
        assert_eq!(result.len(), 1);
        let long = format!("{}.", "x".repeat(500));
        assert_eq!(chunk(&long, "s", 400, 0)[0].text, long);
    }
}
