from flask import jsonify

LABELS = {
    'FILE_TOO_LARGE':'文件超过 256 KiB', 'FILE_EMPTY':'文件没有内容', 'FILE_BLANK':'文件只有空白',
    'HEADER_ONLY':'文件只有标题行', 'HEADER_MISMATCH':'列名与字段字典不一致', 'ENCODING_INVALID':'请使用 UTF-8 CSV',
    'CSV_MALFORMED':'CSV 引号或行格式异常', 'ROW_LIMIT':'文件超过 2000 行', 'FILE_REQUIRED':'请选择 CSV 文件',
    'RUN_NOT_FOUND':'批次不存在', 'REVIEW_FIELDS':'请填写 3 至 200 字复核意见', 'STALE_REVIEW':'批次已更新，请刷新',
    'RUN_FINALIZED':'批次已签发', 'UNRESOLVED_ISSUES':'存在待处理差异', 'SAMPLE_UNKNOWN':'样例不存在', 'STAGE_UNKNOWN':'处理阶段不存在',
    'RECOGNITION_FIELDS':'请补全互认登记字段', 'RECOGNITION_EVENT_UNKNOWN':'未知的互认事件类型',
    'GROUP_FIELDS':'分组核验结论须为布尔值', 'AUTHORITY_FIELDS':'权威编号须为非负整数',
    'GROUP_NOT_FOUND':'分组尚未登记', 'SELF_RECOGNITION':'不能与自身建立互认',
    'CLAIM_NOT_FOUND':'互认关系不存在或已撤销', 'CLAIM_REVOKED':'该互认编号已撤销，请改用新编号',
    'STALE_RECOGNITION':'更正已入账，请刷新后重算签发',
    'GROUP_NOT_RELEASABLE':'该组仍被互认冲突牵连或核验未通过，暂缓签发',
}


def response(error):
    code = error.code
    status = 404 if code in {'RUN_NOT_FOUND','SAMPLE_UNKNOWN','STAGE_UNKNOWN','GROUP_NOT_FOUND','CLAIM_NOT_FOUND'} \
        else 409 if code in {'STALE_REVIEW','RUN_FINALIZED','UNRESOLVED_ISSUES','STALE_RECOGNITION','GROUP_NOT_RELEASABLE'} \
        else 413 if code=='FILE_TOO_LARGE' else 422
    return jsonify(code=code,message=LABELS.get(code,code)),status
