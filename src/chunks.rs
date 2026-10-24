//! Port of the chunking that `seagoat/gitfile.py` used to do in Python. The
//! output, including chunk IDs, must stay byte-for-byte identical, otherwise
//! every existing index is rebuilt.

use sha2::{Digest, Sha256};

use crate::isalnum_table::ISALNUM_RANGES;

const CONTEXT_LINES: usize = 5;
const MAX_LINE_LENGTH: usize = 100;
const MIN_ALPHANUMERIC_CHARACTERS: usize = 4;

pub fn is_alnum(character: char) -> bool {
    let code_point = character as u32;
    ISALNUM_RANGES
        .binary_search_by(|&(first, last)| {
            if last < code_point {
                std::cmp::Ordering::Less
            } else if first > code_point {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

fn has_relevant_data(line: &str) -> bool {
    line.chars()
        .filter(|&character| is_alnum(character))
        .nth(MIN_ALPHANUMERIC_CHARACTERS - 1)
        .is_some()
}

/// Up to `CONTEXT_LINES` lines, walking away from the chunk's line, stopping
/// after the first one that has relevant data.
fn context_lines<'a>(lines: impl Iterator<Item = &'a String>) -> Vec<&'a String> {
    let mut context = Vec::new();
    for line in lines.take(CONTEXT_LINES) {
        context.push(line);
        if has_relevant_data(line) {
            break;
        }
    }
    context
}

fn format_chunk(relevant_lines: &[&String], metadata: &str) -> String {
    let truncated: Vec<String> = relevant_lines
        .iter()
        .map(|line| line.chars().take(MAX_LINE_LENGTH).collect())
        .collect();
    truncated.join("\n") + metadata
}

fn chunk_id(path: &str, object_id: &str, codeline: usize, chunk: &str) -> String {
    let text = format!(
        "\n        Path: {path}\n        Object ID: {object_id}\n        Code line: {codeline}\n        Chunk: {chunk}\n        "
    );
    Sha256::digest(text.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub fn get_chunks(
    path: &str,
    object_id: &str,
    lines: &[String],
    metadata: &str,
) -> Vec<(usize, String, String)> {
    lines
        .iter()
        .enumerate()
        .filter(|(_, line)| has_relevant_data(line))
        .map(|(index, line)| {
            let mut relevant_lines = context_lines(lines[..index].iter().rev());
            relevant_lines.reverse();
            relevant_lines.push(line);
            relevant_lines.extend(context_lines(lines[index + 1..].iter()));

            let codeline = index + 1;
            let chunk = format_chunk(&relevant_lines, metadata);
            let id = chunk_id(path, object_id, codeline, &chunk);
            (codeline, chunk, id)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn needs_four_alphanumeric_characters() {
        assert!(!has_relevant_data("a b c"));
        assert!(has_relevant_data("a b c d"));
    }

    #[test]
    fn combining_marks_are_not_alphanumeric() {
        // U+0903 DEVANAGARI SIGN VISARGA: Rust counts it as alphabetic,
        // Python's str.isalnum() does not.
        assert!(!is_alnum('\u{0903}'));
        assert!('\u{0903}'.is_alphanumeric());
    }

    #[test]
    fn context_stops_at_relevant_line() {
        let lines: Vec<String> = ["first line", "}", "", "middle line", "{", "last line"]
            .iter()
            .map(|line| line.to_string())
            .collect();
        let chunks = get_chunks("a.py", "abc", &lines, "");
        let middle = chunks
            .iter()
            .find(|(codeline, _, _)| *codeline == 4)
            .unwrap();
        assert_eq!(middle.1, "first line\n}\n\nmiddle line\n{\nlast line");
    }
}
