import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ExportDialog } from "./ExportDialog";

const download = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/export-client", () => ({
    downloadNetworkImage: (...args: unknown[]) => download(...args),
}));

beforeEach(() => download.mockClear());

function chooseObjectViews() {
    fireEvent.click(screen.getByLabelText(/PNG/i, { selector: "input[type=radio]" }));
    fireEvent.change(screen.getByRole("combobox", { name: /What to export/i }), {
        target: { value: "objects" },
    });
}

describe("ExportDialog image export", () => {
    it("has no checkbox for the overview picture", () => {
        render(<ExportDialog onClose={() => {}} />);
        chooseObjectViews();

        expect(screen.queryByLabelText(/overview/i)).not.toBeInTheDocument();
        expect(screen.getByText(/overview of the whole network is always included/i)).toBeInTheDocument();
    });

    it("exports object views with the parameter table and never asks the server to drop the overview", async () => {
        render(<ExportDialog onClose={() => {}} />);
        chooseObjectViews();
        fireEvent.click(screen.getByRole("button", { name: /export/i }));

        await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
        const options = download.mock.calls[0][1] as Record<string, unknown>;
        expect(options).toMatchObject({ scope: "objects", format: "zip", include_parameters: true });
        expect(options).not.toHaveProperty("include_overview");
    });
});
