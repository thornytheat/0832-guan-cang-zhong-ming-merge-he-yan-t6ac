"""跨组互认签发台的 HTTP 接口。

* GET  /recognition                工作台页面
* GET  /api/recognition             查看各组状态、冲突证据与签发结论
* POST /api/recognition/events      入账更正事件（分组/权威/互认/撤销）
* POST /api/recognition/submissions 同批提交更正与分组签发（更正先入账）
* POST /api/recognition/signoffs    单个分组签发/重签
"""

from flask import Blueprint, current_app, jsonify, render_template, request

from app.business import DomainIssue
from app.recognize.domain import RecognitionError
from app.recognize.store import RecognitionStore

bp = Blueprint('recognition', __name__)


def store():
    return current_app.extensions['recognition']


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise RecognitionError('RECOGNITION_FIELDS')
    return data


@bp.get('/recognition')
def workbench():
    return render_template('recognition.html')


@bp.get('/api/recognition')
def snapshot():
    return jsonify(store().snapshot())


@bp.post('/api/recognition/events')
def admit():
    data = payload()
    events = data.get('events')
    if not isinstance(events, list):
        raise RecognitionError('RECOGNITION_FIELDS')
    sequence = store().admit(events)
    return jsonify({**store().snapshot(), 'sequence': sequence})


@bp.post('/api/recognition/submissions')
def submit():
    data = payload()
    events = data.get('events', [])
    signoffs = data.get('signoffs', [])
    sequence, issued = store().submit(events, signoffs)
    return jsonify({**store().snapshot(), 'sequence': sequence, 'issued': issued})


@bp.post('/api/recognition/signoffs')
def signoff():
    return jsonify(store().signoff(payload()))


@bp.get('/api/recognition/signoffs')
def list_signoffs():
    return jsonify(items=store().list_signoffs())
