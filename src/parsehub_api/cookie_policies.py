from __future__ import annotations

from dataclasses import dataclass

from parsehub.utils.helpers import SecretCookie


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    supported: bool
    required: tuple[str, ...] = ()
    recommended: tuple[str, ...] = ()
    note: str = ""

    def public(self) -> dict:
        return {
            "supported": self.supported,
            "required": list(self.required),
            "recommended": list(self.recommended),
            "note": self.note,
        }


POLICIES: dict[str, CookiePolicy] = {
    "twitter": CookiePolicy(
        True,
        required=("auth_token", "ct0"),
        recommended=("guest_id", "twid"),
        note="auth_token 是登录会话，ct0 同时用于 x-csrf-token 请求头。",
    ),
    "instagram": CookiePolicy(
        True,
        recommended=("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did"),
        note="公开内容可匿名解析；私人或受限内容通常需要 sessionid 和 csrftoken。",
    ),
    "youtube": CookiePolicy(
        True,
        recommended=("SAPISID", "__Secure-3PAPISID", "SID", "HSID", "SSID", "LOGIN_INFO"),
        note="通过 yt-dlp 使用，建议复制 youtube.com 请求中的完整 Cookie。",
    ),
    "bilibili": CookiePolicy(
        True,
        recommended=("SESSDATA", "bili_jct", "DedeUserID", "buvid3", "buvid4"),
        note="主要用于动态、登录内容和 yt-dlp 回退；普通公开视频可能无需 Cookie。",
    ),
    "douyin": CookiePolicy(
        True,
        recommended=("sessionid", "sid_guard", "uid_tt", "passport_csrf_token", "ttwid", "msToken"),
        note="字段随风控变化较快，建议从作品详情请求复制完整 Cookie。",
    ),
    "tiktok": CookiePolicy(
        True,
        recommended=("sessionid", "sid_guard", "uid_tt", "tt_chain_token", "msToken", "odin_tt"),
        note="建议复制完整 Cookie；地区出口和账号常用地区应尽量一致。",
    ),
    "kuaishou": CookiePolicy(
        True,
        required=("did",),
        recommended=("didv", "userId", "kuaishou.server.web_st", "kuaishou.server.web_ph"),
        note="当前 GraphQL 接口缺少 did 时通常直接报“did 未填”。",
    ),
    "xhs": CookiePolicy(
        True,
        recommended=("a1", "web_session", "webId", "gid", "xsecappid"),
        note="登录内容通常需要 web_session；分享链接上的 xsec_token 不是 Cookie，请保留在 URL 中。",
    ),
    "zhihu": CookiePolicy(
        True,
        required=("d_c0",),
        recommended=("z_c0", "_zap", "q_c1"),
        note="d_c0 用于生成 x-zse-96，缺失时解析器无法工作；不要删除值中的引号。",
    ),
}

UNSUPPORTED_POLICY = CookiePolicy(False, note="当前解析器不会读取该平台 Cookie，只能配置平台代理。")


def get_cookie_policy(platform: str) -> CookiePolicy:
    return POLICIES.get(platform, UNSUPPORTED_POLICY)


def validate_cookie(platform: str, cookie: str) -> tuple[list[str], list[str]]:
    policy = get_cookie_policy(platform)
    if not policy.supported:
        return [], []
    values = SecretCookie(cookie).get_value() or {}
    missing_required = [field for field in policy.required if not values.get(field)]
    missing_recommended = [field for field in policy.recommended if not values.get(field)]
    return missing_required, missing_recommended
