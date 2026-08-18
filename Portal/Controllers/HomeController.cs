using System.Diagnostics;
using GridWitness.Portal.Models;
using Microsoft.AspNetCore.Mvc;

namespace GridWitness.Portal.Controllers;

public sealed class HomeController : Controller
{
    public IActionResult Index() => View();

    public IActionResult HowItWorks() => View();

    public IActionResult Privacy() => View();

    public IActionResult Schema() => View();

    public IActionResult Submitters() => View();

    [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
    public IActionResult Error() =>
        View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
}
