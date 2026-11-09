#include <pybind11/pybind11.h>

#include <crownJsonProcessor/CrownJsonProcessor.h>

#include <string>

namespace py = pybind11;

namespace {

[[nodiscard]] std::string processJsonString(const std::string& inputJson)
{
    std::string outputJson;
    {
        py::gil_scoped_release release;
        outputJson = crown::json::processJsonString(inputJson);
    }
    return outputJson;
}

}  // namespace

PYBIND11_MODULE(crown, module)
{
    module.doc() =
        "Python bindings for crownJsonProcessor JSON crown processing.";
    module.def(
        "process_crown_json",
        &processJsonString,
        py::arg("input_json"),
        "Process a JSON string and return the output JSON string.");
}
