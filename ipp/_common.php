<?php
include_once(__DIR__.'/../common.php');

// 꺼진 기능 페이지에 접근하면 메인으로 돌려보냄
function ipp_require_feature($is_on) {
    if (!$is_on) alert('현재 사용하지 않는 기능입니다.', G5_URL);
}