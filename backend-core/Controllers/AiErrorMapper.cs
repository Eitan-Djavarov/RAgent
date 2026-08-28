using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Controllers;

internal static class AiErrorMapper
{
    public static int MapStatusCode(AiServiceException ex) =>
        ex.StatusCode switch
        {
            HttpStatusCode.BadRequest => StatusCodes.Status400BadRequest,
            HttpStatusCode.TooManyRequests => StatusCodes.Status429TooManyRequests,
            HttpStatusCode.RequestTimeout => StatusCodes.Status504GatewayTimeout,
            HttpStatusCode.Unauthorized => StatusCodes.Status401Unauthorized,
            HttpStatusCode.Forbidden => StatusCodes.Status403Forbidden,
            _ => StatusCodes.Status502BadGateway,
        };

    public static ProblemDetailsDto ToProblemDetails(AiServiceException ex, string traceId, string fallbackTitle)
    {
        var statusCode = MapStatusCode(ex);
        var parsed = TryParseBody(ex.ResponseBody);
        var title = statusCode switch
        {
            StatusCodes.Status429TooManyRequests => "Rate limit exceeded",
            StatusCodes.Status400BadRequest => parsed.ErrorCode == "SECURITY_VIOLATION"
                ? "Security guardrail violation"
                : (parsed.Title ?? "Bad request"),
            _ => parsed.Title ?? fallbackTitle,
        };

        return new ProblemDetailsDto(
            Type: $"https://httpstatuses.com/{statusCode}",
            Title: title,
            Status: statusCode,
            Detail: parsed.Detail ?? ex.Message,
            TraceId: traceId,
            ErrorCode: parsed.ErrorCode
                ?? (statusCode == StatusCodes.Status429TooManyRequests ? "RATE_LIMITED" : null),
            Reason: parsed.Reason,
            RetryAfterSeconds: parsed.RetryAfterSeconds
                ?? TryParseRetryAfter(ex.ResponseHeaders));
    }

    public static void ApplyRateLimitHeaders(HttpResponse response, AiServiceException ex, ProblemDetailsDto problem)
    {
        if (problem.Status != StatusCodes.Status429TooManyRequests)
        {
            return;
        }

        var retryAfter = problem.RetryAfterSeconds
            ?? TryParseRetryAfter(ex.ResponseHeaders)
            ?? 60;
        response.Headers["Retry-After"] = retryAfter.ToString();

        if (ex.ResponseHeaders is not null)
        {
            if (ex.ResponseHeaders.TryGetValue("X-RateLimit-Limit", out var limit))
            {
                response.Headers["X-RateLimit-Limit"] = limit;
            }

            if (ex.ResponseHeaders.TryGetValue("X-RateLimit-Remaining", out var remaining))
            {
                response.Headers["X-RateLimit-Remaining"] = remaining;
            }
        }
    }

    private static int? TryParseRetryAfter(IReadOnlyDictionary<string, string>? headers)
    {
        if (headers is null)
        {
            return null;
        }

        if (!headers.TryGetValue("Retry-After", out var raw))
        {
            return null;
        }

        return int.TryParse(raw, out var seconds) ? seconds : null;
    }

    private static (string? Title, string? Detail, string? ErrorCode, string? Reason, int? RetryAfterSeconds) TryParseBody(
        string? body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return (null, null, null, null, null);
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            string? title = root.TryGetProperty("title", out var titleEl) ? titleEl.GetString() : null;
            string? detail = root.TryGetProperty("detail", out var detailEl) ? detailEl.GetString() : null;
            string? errorCode = root.TryGetProperty("errorCode", out var codeEl) ? codeEl.GetString() : null;
            string? reason = root.TryGetProperty("reason", out var reasonEl) ? reasonEl.GetString() : null;
            int? retry = null;
            if (root.TryGetProperty("retryAfterSeconds", out var retryEl)
                && retryEl.TryGetInt32(out var retryValue))
            {
                retry = retryValue;
            }

            return (title, detail, errorCode, reason, retry);
        }
        catch (JsonException)
        {
            return (null, null, null, null, null);
        }
    }
}
