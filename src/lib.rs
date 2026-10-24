//! Native parts of SeaGOAT, exposed to Python as `seagoat._native`.

mod chunks;
mod isalnum_table;

use pyo3::prelude::*;

/// Split a file into chunks: one per line that has relevant data, with up to
/// five lines of context on each side.
///
/// Returns `(codeline, chunk, chunk_id)` tuples, where `codeline` is 1-based.
#[pyfunction]
fn get_chunks(
    path: &str,
    object_id: &str,
    lines: Vec<String>,
    metadata: &str,
) -> Vec<(usize, String, String)> {
    chunks::get_chunks(path, object_id, &lines, metadata)
}

/// Same as Python's `str.isalnum()` for a single character, as of the Unicode
/// version in `UNICODE_VERSION`.
#[pyfunction]
fn is_alnum(character: char) -> bool {
    chunks::is_alnum(character)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(get_chunks, module)?)?;
    module.add_function(wrap_pyfunction!(is_alnum, module)?)?;
    module.add("UNICODE_VERSION", isalnum_table::UNICODE_VERSION)?;
    Ok(())
}
