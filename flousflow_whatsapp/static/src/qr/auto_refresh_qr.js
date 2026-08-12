/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { imageUrl } from "@web/core/utils/urls";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const REFRESH_INTERVAL_MS = 5000;

export class WhatsappAutoRefreshQr extends Component {
    static template = "flousflow_whatsapp.WhatsappAutoRefreshQr";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.timer = null;
        this.refreshing = false;
        this.state = useState({
            connectorState: this.props.record.data.state,
            hasQr: Boolean(this.props.record.data[this.props.name]),
            cacheKey: this.props.record.data.write_date || Date.now(),
        });
        onMounted(() => {
            void this.refresh();
            this.timer = setInterval(() => void this.refresh(), REFRESH_INTERVAL_MS);
        });
        onWillUnmount(() => {
            if (this.timer) {
                clearInterval(this.timer);
            }
        });
    }

    get qrUrl() {
        return imageUrl(
            this.props.record.resModel,
            this.props.record.resId,
            this.props.name,
            { unique: this.state.cacheKey }
        );
    }

    async refresh() {
        if (this.refreshing || !this.props.record.resId) {
            return;
        }
        this.refreshing = true;
        try {
            const [number] = await this.orm.read(
                this.props.record.resModel,
                [this.props.record.resId],
                ["state", "write_date"]
            );
            if (!number) {
                return;
            }
            this.state.connectorState = number.state;
            this.state.hasQr = number.state === "qr";
            this.state.cacheKey = number.write_date || Date.now();
        } catch {
            // Keep the last valid QR visible during a transient polling failure.
        } finally {
            this.refreshing = false;
        }
    }
}

export const whatsappAutoRefreshQr = {
    component: WhatsappAutoRefreshQr,
    supportedTypes: ["binary"],
    fieldDependencies: [
        { name: "state", type: "selection" },
        { name: "write_date", type: "datetime" },
    ],
    isEmpty: () => false,
};

registry.category("fields").add("whatsapp_auto_refresh_qr", whatsappAutoRefreshQr);
