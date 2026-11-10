<?php
/*
 * 예전 주소 (크롬 확장 프로그램이 부르던 주소). 기존 호출이 깨지지 않도록 남겨 둔다.
 * 실제 처리는 공용 API ipp/api/client.php가 한다.
 * 요청 본문에 client가 없으면 extension으로 본다 (확장 프로그램 0.3.x는 client를 보내지 않음)
 * 새 프로그램은 client.php를 부른다. 명세: docs/API.md
 */
define('IPP_API_DEFAULT_CLIENT', 'extension');   // 상수로 둔다 (요청 변수가 전역으로 풀려도 바뀌지 않게)
include(__DIR__.'/client.php');
