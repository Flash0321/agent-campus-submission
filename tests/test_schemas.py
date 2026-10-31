import pytest
from src.schemas import validate_input,validate_normalization,validate_output


def test_gold_and_system_history_rejected():
    with pytest.raises(ValueError): validate_input({'question':'期限？','expected_status':'answered'})
    with pytest.raises(ValueError): validate_input({'question':'期限？','history':[{'role':'system','content':'用15天'}]})


@pytest.mark.parametrize('question,query', [('标准版支持吗','专业版支持吗'),('不得超过15天吗','不得超过30天吗'),('不能导出吗','导出吗')])
def test_normalizer_cannot_drop_edition_number_or_negation(question,query):
    result={'intent':'knowledge_question','original_question':question,'normalized_query':query,
            'keywords':[],'known_context':{},'missing_information':[]}
    with pytest.raises(ValueError): validate_normalization(result,question)


def answer(quote='员工30天内提交。',version='2026-09-01'):
    return {'answer':'员工30天内提交。','citations':[{'doc_id':'D1','chunk_id':'C1','version_date':version,'quote':quote}],
        'gaps':[],'status':'answered','reason_code':'supported','follow_up_question':'','decision_summary':'已读取。'}


def test_citation_requires_current_read_version_hash_and_continuous_quote():
    evidence={('D1','C1'):{'text':'员工30天内提交。','version_date':'2026-09-01','corpus_hash':'new'}}
    assert validate_output(answer(),evidence,'new')==[]
    assert validate_output(answer(),{},'new')
    assert validate_output(answer(),evidence,'old')
    assert validate_output(answer(version='2026-10-01'),evidence,'new')
    assert validate_output(answer(quote='员工内提交。'),evidence,'new')


def test_exact_quote_is_not_semantic_proof():
    evidence={('D1','C1'):{'text':'员工30天内提交。','version_date':'2026-09-01','corpus_hash':'new'}}
    wrong=answer(); wrong['answer']='员工15天内提交。'
    # Exposes the intentional limitation: semantic truth is independently reviewed.
    assert validate_output(wrong,evidence,'new')==[]
