import ast
import unittest
from pathlib import Path


class AdminApprovalsContractTest(unittest.TestCase):
    """Static AST-based tests for admin_approvals module contract."""

    MODULE_PATH = Path(__file__).parent.parent / "app" / "admin_approvals.py"

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = cls.MODULE_PATH.read_text()
        cls.tree = ast.parse(cls.source, filename=str(cls.MODULE_PATH))

    def test_no_CreateApprovalPayload_class(self) -> None:
        """CreateApprovalPayload must be removed from the module."""
        classes = [node for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)]
        class_names = [c.name for c in classes]
        self.assertNotIn("CreateApprovalPayload", class_names)

    def test_create_approval_unavailable_function_exists(self) -> None:
        """create_approval_unavailable must exist as POST 410 handler."""
        functions = [node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)]
        function_names = [f.name for f in functions]
        self.assertIn("create_approval_unavailable", function_names)

    def test_create_approval_unavailable_has_no_parameters(self) -> None:
        """create_approval_unavailable must accept no parameters."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_approval_unavailable":
                self.assertEqual(len(node.args.posonlyargs), 0, "posonlyargs must be empty")
                self.assertEqual(len(node.args.args), 0, "args must be empty")
                self.assertEqual(len(node.args.kwonlyargs), 0, "kwonlyargs must be empty")
                self.assertIsNone(node.args.kwarg, "kwarg must be None")
                self.assertIsNone(node.args.vararg, "vararg must be None")
                return
        self.fail("create_approval_unavailable not found")

    def test_create_approval_unavailable_has_post_410_decorator(self) -> None:
        """create_approval_unavailable must have @router.post with status_code=410."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_approval_unavailable":
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Attribute):
                            if decorator.func.attr == "post":
                                for keyword in decorator.keywords:
                                    if keyword.arg == "status_code":
                                        if isinstance(keyword.value, ast.Attribute):
                                            self.assertEqual(keyword.value.attr, "HTTP_410_GONE")
                                        return
                self.fail("@router.post with status_code=HTTP_410_GONE not found")

    def test_create_approval_unavailable_raises_http_exception_410(self) -> None:
        """create_approval_unavailable must raise HTTPException with 410 status and exact detail."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_approval_unavailable":
                for child in ast.walk(node):
                    if isinstance(child, ast.Raise):
                        if isinstance(child.exc, ast.Call):
                            if isinstance(child.exc.func, ast.Name) and child.exc.func.id == "HTTPException":
                                status_found = False
                                detail_found = False
                                for keyword in child.exc.keywords:
                                    if keyword.arg == "status_code":
                                        if isinstance(keyword.value, ast.Attribute):
                                            self.assertEqual(keyword.value.attr, "HTTP_410_GONE")
                                            status_found = True
                                        continue
                                    if keyword.arg == "detail":
                                        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                                            self.assertEqual(keyword.value.value, "Generic approval creation is unavailable. Use a domain-specific endpoint.")
                                            detail_found = True
                                        continue
                                self.assertTrue(status_found, "status_code HTTP_410_GONE not found")
                                self.assertTrue(detail_found, "detail with expected text not found")
                                return
        self.fail("create_approval_unavailable not found or does not raise HTTPException")

    def test_no_create_approval_function(self) -> None:
        """Old create_approval function must be removed."""
        functions = [node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)]
        function_names = [f.name for f in functions]
        self.assertNotIn("create_approval", function_names)

    def test_no_AdminApprovalRequest_creation_in_approvals_module(self) -> None:
        """Module must not create AdminApprovalRequest instances after closing generic endpoint."""
        self.assertNotIn("AdminApprovalRequest(", self.source)


if __name__ == "__main__":
    unittest.main()
