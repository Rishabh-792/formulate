"""Formulate playground.

Run:  streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo-root import

from formulate.errors import FormulateError
from formulate.interpreter import get_interpreter
from formulate.llm import get_settings
from formulate.pipeline import run_from_spec

_DEFAULT = (
    "Meridian Woodworks builds chairs, tables, and desks. Every product "
    "passes through two machines: cutting and assembly. A chair needs 1 "
    "cutting hour and 2 assembly hours; a table needs 3 and 2; a desk needs "
    "2 and 3. Cutting has 160 hours per week, assembly has 250. Profit per "
    "unit: 25 chair, 110 table, 75 desk. The market absorbs at most 100 "
    "chairs, 20 tables, 30 desks. Maximize weekly profit."
)

st.set_page_config(page_title="Formulate", layout="wide")
st.title("Formulate")
st.caption(
    f"LLMs at the boundary, a typed contract in the middle, a deterministic "
    f"compiler at the core — running in **{get_settings().mode}** mode."
)

problem = st.text_area("Describe your optimization problem", _DEFAULT, height=180)

if st.button("Formulate & solve", type="primary"):
    try:
        with st.spinner("interpreting..."):
            spec = get_interpreter().interpret(problem)
        with st.spinner("validating, compiling, solving..."):
            result = run_from_spec(spec)
    except FormulateError as exc:
        st.error(str(exc))
        st.stop()

    left, right = st.columns(2)
    with left:
        st.subheader("Model spec (the typed contract)")
        st.json(spec.model_dump())
        st.subheader("Validation")
        st.code(result.validation.summary())
        if result.transforms:
            st.subheader("Linearization")
            for note in result.transforms:
                st.write(f"`{note.transform}` at {note.location}: {note.detail}")
    with right:
        st.subheader("Generated Pyomo model")
        st.code(result.pyomo_source, language="python")
        st.subheader(f"Solution — {result.solution.status} ({result.solution.solver})")
        if result.solution.objective is not None:
            st.metric("Objective", f"{result.solution.objective:,.2f}")
        rows = [
            {"variable": name, "index": idx, "value": val}
            for name, values in result.solution.variables.items()
            for idx, val in values.items()
        ]
        if rows:
            st.dataframe(rows, use_container_width=True)
        st.subheader("Explanation")
        st.write(result.explanation)
