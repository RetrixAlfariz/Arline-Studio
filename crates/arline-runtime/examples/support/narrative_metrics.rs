//! Source-level metrics: repeated chunks never count as additional answers.
use serde_json::{json, Value};
use std::collections::HashSet;

pub fn metrics(rows: &[Value], case: &Value) -> Value {
    let mut seen = HashSet::new();
    let ids: Vec<_> = rows
        .iter()
        .filter_map(|r| r["source_id"].as_str())
        .filter(|id| seen.insert(*id))
        .collect();
    let relevant: HashSet<_> = case["relevant"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let forbidden: HashSet<_> = case["forbidden"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let contradicted: HashSet<_> = case["contradicted"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let recall = |k: usize| {
        if relevant.is_empty() {
            Value::Null
        } else {
            json!(
                ids.iter()
                    .take(k)
                    .filter(|id| relevant.contains(**id))
                    .count() as f64
                    / relevant.len() as f64
            )
        }
    };
    let dcg: f64 = ids
        .iter()
        .take(10)
        .enumerate()
        .filter(|(_, id)| relevant.contains(**id))
        .map(|(i, _)| 1.0 / ((i + 2) as f64).log2())
        .sum();
    let ideal: f64 = (0..relevant.len().min(10))
        .map(|i| 1.0 / ((i + 2) as f64).log2())
        .sum();
    let first = ids.iter().take(10).position(|id| relevant.contains(*id));
    json!({"recall_at_5":recall(5),"recall_at_10":recall(10),
        "mrr_at_10":if relevant.is_empty(){Value::Null}else{json!(first.map_or(0.0,|i|1.0/(i+1) as f64))},
        "ndcg_at_10":if ideal==0.0{Value::Null}else{json!(dcg/ideal)},
        "source_ids":ids,"source_count":ids.len(),"selected_chunks":rows.len(),
        "forbidden_sources":ids.iter().filter(|id|forbidden.contains(**id)).count(),
        "contradicted_sources":ids.iter().filter(|id|contradicted.contains(**id)).count(),
        "unjudged_sources":ids.iter().filter(|id| !relevant.contains(**id) && !forbidden.contains(**id) && !contradicted.contains(**id)).count(),
        "no_answer":case["no_answer"],"retrieval_abstained":rows.is_empty(),
        "no_answer_abstention_correct":if case["no_answer"]==true{json!(rows.is_empty())}else{Value::Null},
        "answerable_evidence_found":if relevant.is_empty(){Value::Null}else{json!(first.is_some())}})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn duplicate_chunks_and_unanswerable_queries_do_not_inflate_metrics() {
        let rows = vec![
            json!({"source_id":"a"}),
            json!({"source_id":"a"}),
            json!({"source_id":"bad"}),
        ];
        let c =
            json!({"relevant":["a","b"],"forbidden":["bad"],"contradicted":[],"no_answer":false});
        let m = metrics(&rows, &c);
        assert_eq!(m["recall_at_5"], 0.5);
        assert_eq!(m["forbidden_sources"], 1);
        assert_eq!(m["source_count"], 2);
        let no = json!({"relevant":[],"forbidden":[],"contradicted":[],"no_answer":true});
        let m = metrics(&rows, &no);
        assert!(m["ndcg_at_10"].is_null());
        assert_eq!(m["no_answer_abstention_correct"], false);
        assert_eq!(metrics(&[], &no)["no_answer_abstention_correct"], true);
    }
}
