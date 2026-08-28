using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Data;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Controllers;

[ApiController]
[Route("api/[controller]")]
public sealed class HealthController : ControllerBase
{
    private readonly AppDbContext _dbContext;
    private readonly IAiServiceClient _aiServiceClient;

    public HealthController(AppDbContext dbContext, IAiServiceClient aiServiceClient)
    {
        _dbContext = dbContext;
        _aiServiceClient = aiServiceClient;
    }

    [HttpGet]
    [ProducesResponseType(typeof(HealthResponseDto), StatusCodes.Status200OK)]
    public ActionResult<HealthResponseDto> Get()
    {
        return Ok(new HealthResponseDto(
            "Healthy",
            "backend-core",
            DateTimeOffset.UtcNow));
    }

    [HttpGet("ready")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> ReadyAsync(CancellationToken cancellationToken)
    {
        var databaseOk = await CanConnectToDatabaseAsync(cancellationToken);
        var aiOk = await _aiServiceClient.IsHealthyAsync(cancellationToken);

        var payload = new
        {
            status = databaseOk && aiOk ? "Ready" : "Degraded",
            checks = new
            {
                postgres = databaseOk,
                aiService = aiOk,
            },
            timestamp = DateTimeOffset.UtcNow,
        };

        if (!databaseOk)
        {
            return StatusCode(StatusCodes.Status503ServiceUnavailable, payload);
        }

        return Ok(payload);
    }

    private async Task<bool> CanConnectToDatabaseAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _dbContext.Database.CanConnectAsync(cancellationToken);
        }
        catch (Exception)
        {
            return false;
        }
    }
}
